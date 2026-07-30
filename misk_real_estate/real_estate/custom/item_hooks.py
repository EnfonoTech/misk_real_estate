from misk_real_estate.utils.company import resolve_unit_company


def validate(doc, method=None):
    _default_company_from_item_group(doc)


def _default_company_from_item_group(doc):
    """A real estate unit's own company defaults from its Item Group
    (Building), falling back to Misk Real Estate Settings' default company
    when the Building itself has none set. Never overrides a value the user
    (or the building import) already set."""
    if not doc.is_unit or doc.company:
        return
    doc.company = resolve_unit_company(doc.item_group)
