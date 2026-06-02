import React from 'react';

type HermesLogoProps = {
  className?: string;
};

// Hermes/Mercury alchemical symbol (☿): crescent over a circle over a cross.
// Inline SVG with currentColor so it adapts to theme + text color.
const HermesLogo = ({ className = 'w-5 h-5' }: HermesLogoProps) => (
  <svg
    viewBox="0 0 24 24"
    className={className}
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-label="Hermes"
  >
    <circle cx="12" cy="10.5" r="3.8" />
    <path d="M8.4 3.2a3.6 3.6 0 0 0 7.2 0" />
    <line x1="12" y1="14.3" x2="12" y2="21" />
    <line x1="9" y1="18" x2="15" y2="18" />
  </svg>
);

export default HermesLogo;
