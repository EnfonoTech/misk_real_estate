# apps/misk_real_estate/misk_real_estate/voucher_entry/doctype/bank_payment/bank_payment.py

from misk_real_estate.voucher_entry.voucher_base import VoucherBase


class BankPayment(VoucherBase):
    """Money out of a bank account: credit the bank account, debit the lines."""

    CONTROL_FIELD = "bank_account"
    CONTROL_SIDE = "credit"
    JE_VOUCHER_TYPE = "Bank Entry"
    DIRECTION = "Payment"
