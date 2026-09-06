// bd:shotockviz-474 — pure validation for the "add horizontal level" form
// (AddSrLevelModal.tsx). Same pattern as formValidation.ts: no library,
// inline errors instead of a silent-return on invalid submit (ADR-UH-003).
//
// Deliberately a standalone module (no `@/store/*` aliases) so it is
// importable by the plain Node test runner with zero build step, matching
// srLevelColor.ts / syncSrPriceLines.ts.

/**
 * Validate the raw text-input price for a new S/R level.
 * Mirrors the backend's `SRLevelCreate.price: float = Field(gt=0)` —
 * client-side rejection is a UX nicety, the server is still the real gate.
 */
export function validateSrLevelPrice(raw: string): string | null {
    if (raw.trim() === '') return 'กรุณาระบุราคา';
    const n = Number(raw);
    if (!Number.isFinite(n) || n <= 0) return 'ราคาต้องเป็นตัวเลขมากกว่า 0';
    return null;
}
