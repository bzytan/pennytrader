class MoomooError(Exception):
    def __init__(self, message: str, error_code: int = -1) -> None:
        super().__init__(message)
        self.error_code = error_code


class MoomooConnectionError(MoomooError): pass
class MoomooAuthenticationError(MoomooError): pass
class MoomooOrderError(MoomooError): pass
class MoomooMarketDataError(MoomooError): pass
class MoomooOptionsError(MoomooError): pass
