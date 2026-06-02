class DomainException(Exception):
    """Base class for all domain exceptions"""
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

class EntityNotFoundError(DomainException):
    """Raised when an entity is not found in the domain"""
    pass

class BusinessRuleViolationError(DomainException):
    """Raised when a business rule is violated"""
    pass

class ConflictError(DomainException):
    """Raised when there is a conflict in the domain (e.g. duplicate resource)"""
    pass

class UnauthorizedError(DomainException):
    """Raised when an action is unauthorized at the domain level"""
    pass
