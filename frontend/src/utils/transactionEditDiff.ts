// bd:shotockviz-gij — build the PUT /portfolio/transactions/{id} body as a
// diff against the saved row, not the full form.
//
// Two independent reasons this has to be a diff, not "always send the full
// set":
//   1. `fx_rate` (bd:shotockviz-fnn) is never touched here — omitted from
//      TransactionForm entirely — so it is never present in this patch
//      either. TransactionUpdate treats a present `fx_rate` as an explicit
//      correction, never a recomputed side effect of editing qty/price/date
//      (backend/api/routes/portfolio.py:399-402).
//   2. `date` (backend/models/schemas.py TransactionUpdate) currently
//      resolves its own type annotation to NoneType — a field literally
//      named `date` typed `Optional[date] = None` shadows the `date` class
//      it is supposed to mean, confirmed with
//      `TransactionUpdate.model_fields['date'].annotation is NoneType`, and
//      reproduced with a bare `class M(BaseModel): date: Optional[date] =
//      None` inside the backend container — TransactionCreate.date (no
//      default) is unaffected. Any PUT body containing a `date` key 422s no
//      matter what value it holds. Tracked as bd:shotockviz-qml
//      (backend-owned; this frontend agent could not fix it). The edit form
//      keeps the date input disabled until that lands, so this diff never
//      has to omit an *intentional* date change silently — there is no path
//      by which the user's edited date differs from the original one.
export interface OriginalTransaction {
    qty: number;
    price: number;
    fee?: number | null;
    currency?: string | null;
    date: string;
    note?: string | null;
}

export interface TransactionFormValues {
    qty: string;
    price: string;
    fee: string;
    currency: string;
    date: string;
    note: string;
}

/** Empty object = nothing to send; caller should treat that as a no-op success. */
export function buildTransactionUpdatePatch(
    original: OriginalTransaction,
    form: TransactionFormValues
): Record<string, unknown> {
    const patch: Record<string, unknown> = {};

    const qty = parseFloat(form.qty);
    if (!Number.isNaN(qty) && qty !== original.qty) patch.qty = qty;

    const price = parseFloat(form.price);
    if (!Number.isNaN(price) && price !== original.price) patch.price = price;

    const fee = parseFloat(form.fee) || 0;
    if (fee !== (original.fee ?? 0)) patch.fee = fee;

    const currency = (form.currency || 'THB').toUpperCase();
    const originalCurrency = (original.currency || 'THB').toUpperCase();
    if (currency !== originalCurrency) patch.currency = currency;

    if (form.date !== original.date) patch.date = form.date;

    const note = form.note || '';
    const originalNote = original.note || '';
    if (note !== originalNote) patch.note = note;

    return patch;
}
