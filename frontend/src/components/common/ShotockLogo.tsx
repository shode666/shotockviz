import React from 'react';

// Real brand mark — raster, simplified "S" glyph, purple-gradient background
// baked in (per assets/brand/icons/README.md: full detailed mark blurs below
// ~64px, so icons at/under that threshold ship the simplified glyph instead).
// Two call sites use two different pre-baked sizes; `variant` picks the
// right source file. className/style still apply to the <img> itself, so
// existing call-site decoration (rounded corners, shadow, size) keeps working.
type LogoVariant = 'navbar' | 'login';

const LOGO_SRC: Record<LogoVariant, string> = {
    navbar: '/icon-rounded-32.png', // 32px native, matches Navbar's w-8 h-8
    login: '/icon-rounded-64.png',  // 64px native, closest to LoginPage's 60px
};

export default function ShotockLogo({
    variant = 'navbar',
    className = "w-8 h-8",
    style
}: {
    variant?: LogoVariant;
    className?: string;
    style?: React.CSSProperties
}) {
    return (
        <img
            src={LOGO_SRC[variant]}
            alt="ShotockViz"
            className={className}
            style={{ objectFit: 'contain', ...style }}
        />
    );
}
