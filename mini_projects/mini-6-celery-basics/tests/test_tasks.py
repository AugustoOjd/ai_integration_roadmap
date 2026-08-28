from app import tasks


# .apply() ejecuta la tarea en ESTE proceso y devuelve un EagerResult, sin
# broker ni worker. Es el equivalente de .delay() para tests.
def test_slow_double_duplica(monkeypatch):
    # El sleep es didáctico, no parte de la lógica: fuera en tests.
    monkeypatch.setattr(tasks.time, "sleep", lambda _: None)

    resultado = tasks.slow_double.apply(args=[21])

    assert resultado.successful()
    assert resultado.result["input"] == 21
    assert resultado.result["result"] == 42


def test_flaky_sin_fallos_no_reintenta(monkeypatch):
    monkeypatch.setattr(tasks.time, "sleep", lambda _: None)

    resultado = tasks.flaky.apply(args=[0])

    assert resultado.successful()
    assert resultado.result["intentos"] == 1


def test_flaky_pide_reintento_con_backoff(monkeypatch):
    """El `self` de la tarea ES el objeto `flaky`, así que se le puede
    parchear .retry() y observar con qué countdown lo llamaría."""
    llamadas = []

    def fake_retry(exc=None, countdown=None, **kwargs):
        llamadas.append(countdown)
        # El retry real corta la ejecución levantando Retry; imitamos eso.
        raise RuntimeError(str(exc))

    monkeypatch.setattr(tasks.flaky, "retry", fake_retry)

    # retries=0 y fail_times=2 -> debe pedir reintento con countdown 2**0 = 1.
    tasks.flaky.apply(args=[2])

    assert llamadas == [1]


def test_flaky_configurada_con_tres_reintentos():
    # 3 reintentos = 4 ejecuciones. Fijarlo en un test evita que alguien lo
    # cambie sin querer al tocar el decorador.
    assert tasks.flaky.max_retries == 3
