class AppError(Exception):
    """Base exception for the application."""

    def __init__(self, message: str = "", code: str = "APP_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class EmailFetchError(AppError):
    def __init__(self, message: str = "Failed to fetch emails"):
        super().__init__(message, "EMAIL_FETCH_ERROR")


class ParsingError(AppError):
    def __init__(self, message: str = "Failed to parse document"):
        super().__init__(message, "PARSING_ERROR")


class OCRError(ParsingError):
    def __init__(self, message: str = "OCR processing failed"):
        super().__init__(message)
        self.code = "OCR_ERROR"


class ValidationError(AppError):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, "VALIDATION_ERROR")


class ZohoError(AppError):
    def __init__(self, message: str = "Zoho API error"):
        super().__init__(message, "ZOHO_ERROR")


class ZohoAuthError(ZohoError):
    def __init__(self, message: str = "Zoho authentication failed"):
        super().__init__(message)
        self.code = "ZOHO_AUTH_ERROR"


class ZohoRateLimitError(ZohoError):
    def __init__(self, message: str = "Zoho rate limit exceeded"):
        super().__init__(message)
        self.code = "ZOHO_RATE_LIMIT"


class VendorLookupError(AppError):
    def __init__(self, message: str = "Vendor lookup failed"):
        super().__init__(message, "VENDOR_LOOKUP_ERROR")


class RuleEngineError(AppError):
    def __init__(self, message: str = "Rule engine error"):
        super().__init__(message, "RULE_ENGINE_ERROR")


class IntegrationError(AppError):
    def __init__(self, message: str = "Integration error"):
        super().__init__(message, "INTEGRATION_ERROR")
