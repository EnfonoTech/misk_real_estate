# apps/misk_real_estate/misk_real_estate/voucher_entry/doctype/cash_payment/cash_payment.py

from misk_real_estate.voucher_entry.voucher_base import VoucherBase


class CashPayment(VoucherBase):
    """Money out of a cash account: credit the cash account, debit the lines."""

    CONTROL_FIELD = "cash_account"
    CONTROL_SIDE = "credit"
    JE_VOUCHER_TYPE = "Cash Entry"
    DIRECTION = "Payment"
