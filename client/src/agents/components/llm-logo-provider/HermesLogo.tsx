import { useTheme } from '../../contexts/ThemeContext';

type HermesLogoProps = {
  className?: string;
};

// Nous Research Hermes — official brand artwork. The source is black linework
// on a light field; the dark variant is luminance-inverted so it stays legible
// on a dark background (same dual-asset pattern as the Cursor logo).
const HermesLogo = ({ className = 'w-5 h-5' }: HermesLogoProps) => {
  const { isDarkMode } = useTheme();

  return (
    <img
      src={`${import.meta.env.BASE_URL}icons/${isDarkMode ? 'hermes-white.png' : 'hermes.png'}`}
      alt="Hermes"
      className={className}
    />
  );
};

export default HermesLogo;
