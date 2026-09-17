# apps/misk_real_estate/misk_real_estate/voucher_entry/doctype/bank_receipt/bank_receipt.py

from misk_real_estate.voucher_entry.voucher_base import VoucherBase


class BankReceipt(VoucherBase):
    """Money into a bank account: debit the bank account, credit the lines."""

    CONTROL_FIELD = "bank_account"
    CONTROL_SIDE = "debit"
    JE_VOUCHER_TYPE = "Bank Entry"
    DIRECTION = "Receipt"
