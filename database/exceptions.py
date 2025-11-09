class DatabaseConnectionError(Exception):
    """
    Raised when there is an issue with the database connection.
    This could be due to a network error, authentication failure, or other connection-related issues.
    """
    pass


class DatabaseOperationError(Exception):
    """
    Raised when a database operation fails.
    This could be due to a query error, constraint violation, or other operation-related issues.
    """
    pass