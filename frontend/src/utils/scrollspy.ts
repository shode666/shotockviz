/**
 * Pure scrollspy logic — given the top offsets of each section (in document/
 * container order) and the current scroll position, returns the index of the
 * section that should be marked "current" in a side-nav.
 *
 * Rule: the current section is the last one whose top has been scrolled past
 * (top <= scrollY). At scrollY = 0 this returns 0 (first section), matching
 * the old hardcoded `i === 0` default.
 */
export function getCurrentSection(sectionTops: number[], scrollY: number): number {
    if (sectionTops.length === 0) return 0;

    let current = 0;
    for (let i = 0; i < sectionTops.length; i++) {
        if (scrollY >= sectionTops[i]) {
            current = i;
        }
    }
    return current;
}
