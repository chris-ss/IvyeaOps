import React from 'react';

type AgyLogoProps = {
  className?: string;
};

// Antigravity: an object/arrow lifting off a dashed ground line. Inline SVG
// with currentColor so it adapts to theme + text color.
const AgyLogo = ({ className = 'w-5 h-5' }: AgyLogoProps) => (
  <svg
    viewBox="0 0 24 24"
    className={className}
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-label="Antigravity"
  >
    <path d="M12 3.5v10" />
    <path d="M8 7.5 12 3.5l4 4" />
    <path d="M9 15.5v1.7M15 15.5v1.7" />
    <path d="M4.5 20.5h15" strokeDasharray="2.2 2.4" />
  </svg>
);

export default AgyLogo;
