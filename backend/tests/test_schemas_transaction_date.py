"""Regression test for bd:shotockviz-qml.

`TransactionUpdate.date: Optional[date] = None` shadowed the `datetime.date`
import: the field name is identical to its own type, and once a default is
present pydantic v2 resolves the annotation using `vars(cls)` as localns —
which now holds the class attribute `date` (the field's default) instead of
the module-level `date` type. The annotation collapsed to `NoneType` and
every `PUT /portfolio/transactions/{id}` carrying a `date` key 422'd
regardless of value, because the field could never legally hold anything.

This test asserts the *resolved annotation*, not merely that a PUT/model
call succeeds — a `422` was never the failure mode Pydantic reports for "the
annotation is wrong"; it manifested as a validation error on a value that was
actually correct. Asserting the annotation directly is the only check that
catches the shadowing coming back, since a future edit could reintroduce it
in a way that still happens to accept some inputs by coincidence.

`TransactionCreate.date` and `TransactionResponse.date` are REQUIRED (no
`= None` default) and were confirmed unaffected — included here so the same
shadowing pattern is caught immediately if it is ever introduced there too
(e.g. by someone adding a default for an unrelated reason).
"""
from datetime import date

from models.schemas import TransactionCreate, TransactionResponse, TransactionUpdate


def test_transaction_update_date_annotation_is_date_type():
    """The exact failure mode from bd:shotockviz-qml: annotation collapsed to NoneType."""
    annotation = TransactionUpdate.model_fields["date"].annotation
    assert annotation is not type(None), (
        "TransactionUpdate.date annotation resolved to NoneType — the "
        "field name `date` is shadowing the `datetime.date` import again "
        "(bd:shotockviz-qml regression)"
    )
    # Optional[date] unwraps to (date, NoneType) under typing.get_args
    import typing

    args = typing.get_args(annotation) or (annotation,)
    assert date in args, f"expected `date` in resolved annotation args, got {annotation!r}"


def test_transaction_update_date_round_trips_a_real_value():
    """A value-level guard alongside the annotation guard: it must actually parse."""
    parsed = TransactionUpdate(date="2026-01-10")
    assert parsed.date == date(2026, 1, 10)
    assert isinstance(parsed.date, date)


def test_transaction_create_date_annotation_unaffected():
    """Required (no default) field — confirmed not shadowed; guard against regression."""
    annotation = TransactionCreate.model_fields["date"].annotation
    assert annotation is date


def test_transaction_response_date_annotation_unaffected():
    """Required (no default) field — confirmed not shadowed; guard against regression."""
    annotation = TransactionResponse.model_fields["date"].annotation
    assert annotation is date
