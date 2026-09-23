-- Nordix orders schema. Dev-only: the seed drops and recreates everything.
-- Order matters on drop: children (FK holders) before parents.
DROP TABLE IF EXISTS review_decisions;
DROP TABLE IF EXISTS model_audit;
DROP TABLE IF EXISTS refunds;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    -- Human-readable ids ("C-1001") on purpose: the model will read and repeat
    -- them. A UUID is an invitation to hallucinate one character wrong.
    id          text PRIMARY KEY,
    name        text NOT NULL,
    email       text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id            text PRIMARY KEY,                       -- "A17"
    customer_id   text NOT NULL REFERENCES customers (id),
    -- Our view of the order. The carrier's view (in transit, failed visit…)
    -- lives in *their* system and arrives through MCP in phase 4.
    status        text NOT NULL
                  CHECK (status IN ('preparing', 'shipped', 'delivered', 'cancelled')),
    -- Drives the return window: electronics 10 days, books 45, rest 21 (DEV-004).
    category      text NOT NULL
                  CHECK (category IN ('electronics', 'home', 'books', 'food')),
    -- numeric, never float: money arithmetic must be exact. Read as Decimal.
    total         numeric(12, 2) NOT NULL CHECK (total > 0),
    -- "NX" + 10 digits (ENV-011). NULL until the order ships.
    tracking_code text UNIQUE CHECK (tracking_code ~ '^NX[0-9]{10}$'),
    created_at    timestamptz NOT NULL DEFAULT now(),
    -- The return window counts from delivery, not purchase (DEV-004 §1).
    delivered_at  timestamptz,

    -- The DB refuses states that make no sense, whatever the caller is.
    CHECK ((status = 'delivered') = (delivered_at IS NOT NULL))
);

-- customer_orders filters by customer: without this it's a sequential scan.
CREATE INDEX orders_customer_id_idx ON orders (customer_id);

CREATE TABLE refunds (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id         text NOT NULL REFERENCES orders (id),
    amount           numeric(12, 2) NOT NULL CHECK (amount > 0),
    reason           text NOT NULL,
    -- Phase 5: approving twice must not refund twice. The tool derives a key
    -- and the UNIQUE makes the second insert fail — the DB is the last line,
    -- not the model and not the human who clicked "approve".
    idempotency_key  text NOT NULL UNIQUE,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX refunds_order_id_idx ON refunds (order_id);

-- One row per model decision, written by AuditMiddleware (after_model).
-- Append-only: an audit trail you can UPDATE isn't one.
CREATE TABLE model_audit (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- No FK to customers: the audit must record *attempts*, including ones
    -- made with an id that turns out not to exist.
    customer_id    text NOT NULL,
    thread_id      text,                    -- NULL in one-shot mode
    -- What the model decided: ask for tools, answer, or the budget answered
    -- for it (BudgetMiddleware short-circuit).
    decision       text NOT NULL
                   CHECK (decision IN ('tool_calls', 'final', 'budget_exceeded')),
    -- [{"name": ..., "args": {...}}] — what it wanted to do, before it ran.
    tool_calls     jsonb NOT NULL DEFAULT '[]',
    input_tokens   int,
    output_tokens  int,
    model          text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX model_audit_thread_idx ON model_audit (thread_id, created_at);

-- One row per human decision on a paused tool call (HITL). model_audit says
-- what the *model* asked for; this says what a *person* allowed. After an
-- edit the two differ — and the refund that ran matches this table, not that one.
CREATE TABLE review_decisions (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- LangGraph's id for the pause. A resume that gets replayed can't be
    -- recorded twice as two different decisions.
    interrupt_id   text NOT NULL,
    action_index   int  NOT NULL,         -- position in the batch of paused calls
    customer_id    text NOT NULL,
    thread_id      text NOT NULL,
    tool_name      text NOT NULL,
    proposed_args  jsonb NOT NULL,        -- what the model wanted
    decision       text NOT NULL CHECK (decision IN ('approve', 'edit', 'reject')),
    final_args     jsonb,                 -- what will run; NULL when rejected
    message        text,                  -- reject reason shown to the model
    reviewer       text NOT NULL,         -- who. The agent can't know this; the UI can.
    decided_at     timestamptz NOT NULL DEFAULT now(),

    UNIQUE (interrupt_id, action_index),
    CHECK ((decision = 'reject') = (final_args IS NULL))
);
