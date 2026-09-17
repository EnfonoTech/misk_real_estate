# apps/misk_real_estate/misk_real_estate/voucher_entry/doctype/cash_receipt/cash_receipt.py

from misk_real_estate.voucher_entry.voucher_base import VoucherBase


class CashReceipt(VoucherBase):
    """Money into a cash account: debit the cash account, credit the lines."""

    CONTROL_FIELD = "cash_account"
    CONTROL_SIDE = "debit"
    JE_VOUCHER_TYPE = "Cash Entry"
    DIRECTION = "Receipt"
