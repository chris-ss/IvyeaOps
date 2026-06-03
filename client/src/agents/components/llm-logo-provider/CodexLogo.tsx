import React from 'react';
import { useTheme } from '../../contexts/ThemeContext';

type CodexLogoProps = {
  className?: string;
};

const CodexLogo = ({ className = 'w-5 h-5' }: CodexLogoProps) => {
  const { isDarkMode } = useTheme();

  return (
    <img
      src={`${import.meta.env.BASE_URL}icons/${isDarkMode ? 'codex-white.svg' : 'codex.svg'}`}
      alt="Codex"
      className={className}
    />
  );
};

export default CodexLogo;
