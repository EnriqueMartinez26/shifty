"""Registro explicito de TODOS los modelos ORM.

SQLAlchemy resuelve las relaciones declaradas por nombre ("StaffModel") al
configurar los mappers, y configura TODOS los mappers conocidos de una vez.
Un proceso que importa solo parte de los modelos falla en su primera query
con "expression 'StaffModel' failed to locate a name". La API no lo sufria
porque main.py importa todos los routers (y con ellos todos los modelos);
el worker de Celery importa las tasks y cargaba Appointment sin Staff, asi
que ningun job podia consultar la base.

Cualquier proceso que use la base fuera de la API (worker, beat, alembic,
scripts) debe llamar a ``load_all_models()`` antes de la primera query.
``tests/unit/test_model_registry.py`` falla si aparece un modelo nuevo que
no este en esta lista.

CUIDADO con ``alembic revision --autogenerate``: la tabla ``budgets`` SIGUE
EXISTIENDO en la base (con sus politicas RLS) y ya no tiene modelo, asi que
autogenerate va a proponer ``op.drop_table("budgets")``. NO aceptar ese drop
sin querer: el borrado de la tabla es una migracion pendiente y deliberada
(X-04, segundo paso), que se hace recien cuando el usuario confirme que
produccion tiene cero filas. Lo mismo vale para cualquier otra tabla que
quede sin modelo a proposito.
"""

import importlib

MODEL_MODULES: tuple[str, ...] = (
    "infrastructure.persistence.models.appointment",
    "infrastructure.persistence.models.appointment_block",
    "infrastructure.persistence.models.auth_session",
    "infrastructure.persistence.models.schedule",
    "infrastructure.persistence.models.staff",
    "infrastructure.persistence.models.staff_service",
    "infrastructure.persistence.models.user",
    "modules.audit.model",
    "modules.billing.model",
    "modules.ledger.model",
    "modules.legal.model",
    "modules.notifications.model",
    "modules.otp.model",
    "modules.payments.model",
    "modules.promotions.model",
    "modules.services.model",
    "modules.stores.model",
    "modules.waitlist.model",
)


def load_all_models() -> tuple[str, ...]:
    """Importa cada modulo de modelos; idempotente y barato tras la primera vez."""
    for name in MODEL_MODULES:
        importlib.import_module(name)
    return MODEL_MODULES
