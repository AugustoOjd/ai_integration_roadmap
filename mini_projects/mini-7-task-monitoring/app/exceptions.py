class TaskError(Exception):
    """Raíz de los errores propios del dominio.

    Existe para poder atrapar "cualquier fallo que nosotros modelamos" sin
    barrer también los bugs genuinos (un TypeError, un KeyError). Esa distinción
    importa: un bug NO debe reintentarse ni terminar disfrazado de fallo de red;
    debe explotar y verse.
    """


class TransientError(TaskError):
    """Fallo temporal: la misma operación, repetida más tarde, puede funcionar.

    Un 503, un timeout de red, un connection reset, un deadlock de la DB, un 429
    de rate limit. La causa es una condición pasajera del otro lado, no algo malo
    en lo que pedimos.

    Estas clases no tienen comportamiento: su único trabajo es ser un TIPO. Es lo
    que va en `autoretry_for=(TransientError,)`, y con eso la política de
    reintentos queda expresada en la firma de la tarea en vez de escondida en un
    `if` que inspecciona el mensaje del error.
    """


class PermanentError(TaskError):
    """Fallo definitivo: reintentar dará exactamente el mismo resultado.

    Un 400 con payload inválido, un 404, un 401 con credenciales mal
    configuradas, una regla de negocio que no se cumple. Nada de esto se arregla
    esperando.

    Reintentar acá no es "por las dudas": es ocupar 4 veces un slot del worker
    para llegar al mismo lugar, más tarde, con la cola más larga. Y peor, retrasa
    el momento en que te enterás de que algo está roto.

    Notá que NO aparece en ningún `autoretry_for`. Esa ausencia ES la política:
    la tarea falla en el primer intento y va derecho a la dead letter queue.
    """
