type AgyLogoProps = {
  className?: string;
};

// Google Antigravity — official gradient "A" mark. The colored logo reads well
// on both light and dark backgrounds, so a single asset is used (like Gemini).
const AgyLogo = ({ className = 'w-5 h-5' }: AgyLogoProps) => (
  <img
    src={`${import.meta.env.BASE_URL}icons/antigravity.png`}
    alt="Antigravity"
    className={className}
  />
);

export default AgyLogo;
