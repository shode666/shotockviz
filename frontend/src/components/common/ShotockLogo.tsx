import React from 'react';

export default function ShotockLogo({
    className = "w-8 h-8",
    style
}: {
    className?: string;
    style?: React.CSSProperties
}) {
    return (
        <svg viewBox="0 0 128 128" fill="none" xmlns="http://www.w3.org/2000/svg" className={className} style={style}>
            <defs>
                <linearGradient id="sv-grad-logo" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#ffffff" />
                    <stop offset="30%" stopColor="#e9d5ff" />
                    <stop offset="70%" stopColor="#a855f7" />
                    <stop offset="100%" stopColor="#4c1d95" />
                </linearGradient>
                <linearGradient id="bg-glow-logo" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#a855f7" stopOpacity="0.5" />
                    <stop offset="100%" stopColor="#4c1d95" stopOpacity="0" />
                </linearGradient>
                <filter id="glow-logo" x="-20%" y="-20%" width="140%" height="140%">
                    <feDropShadow dx="0" dy="4" stdDeviation="6" floodColor="#a855f7" floodOpacity="0.3" />
                </filter>
            </defs>

            {/* Background Squircle */}
            <rect x="4" y="4" width="120" height="120" rx="32" fill="#0b0d14" />
            <rect x="4" y="4" width="120" height="120" rx="32" fill="none" stroke="url(#bg-glow-logo)" strokeWidth="2" />

            {/* SV Geometric Shapes */}
            <g transform="translate(18, 30) scale(0.55) skewX(-15)" filter="url(#glow-logo)">
                {/* S Top */}
                <path d="M 0 60 Q 0 10 60 10 L 110 10 L 96 34 L 56 34 Q 32 34 30 52 L 70 52 L 56 76 L -4 76 Z" fill="url(#sv-grad-logo)" />
                {/* S Bottom */}
                <polygon points="-16,110 70,88 60,68 -26,90" fill="url(#sv-grad-logo)" />
                {/* V Shape */}
                <polygon points="56,52 82,52 100,100 146,16 172,16 114,124 82,124" fill="url(#sv-grad-logo)" />
            </g>
        </svg>
    );
}
