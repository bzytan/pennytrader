class MoomooConnectionError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code


class MoomooAuthenticationError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code


class MoomooOrderError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code


class MoomooMarketDataError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code


class MoomooOptionsError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code
