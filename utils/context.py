import contextvars

# Context Vars
current_run_id = contextvars.ContextVar("current_run_id", default=None)
current_user_id = contextvars.ContextVar("current_user_id", default=None)
