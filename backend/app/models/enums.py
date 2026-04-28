from enum import Enum


class ParserMode(str, Enum):
    TESSERACT = "tesseract"
    LLAMAPARSE = "llamaparse"


class EmailStatus(str, Enum):
    FETCHED = "FETCHED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ParsingStatus(str, Enum):
    PENDING = "PENDING"
    PARSED = "PARSED"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"


class ZohoPushStatus(str, Enum):
    NOT_PUSHED = "NOT_PUSHED"
    PUSHED = "PUSHED"
    FAILED = "FAILED"


class DraftStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    PUSHED = "PUSHED"
    PUSH_FAILED = "PUSH_FAILED"
    REJECTED = "REJECTED"


class InvoiceSource(str, Enum):
    GMAIL = "gmail"
    STRIPE = "stripe"
    CHARGEBEE = "chargebee"
    MANUAL_UPLOAD = "manual_upload"


class IntegrationPlatform(str, Enum):
    ZOHO = "zoho"
    TALLY = "tally"
    QUICKBOOKS = "quickbooks"
    STRIPE = "stripe"
    CHARGEBEE = "chargebee"


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"
