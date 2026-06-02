import React from 'react';
import { useTheme } from '../../contexts/ThemeContext';

type CursorLogoProps = {
  className?: string;
};

const CursorLogo = ({ className = 'w-5 h-5' }: CursorLogoProps) => {
  const { isDarkMode } = useTheme();

  return (
    <img
      src={`${import.meta.env.BASE_URL}icons/${isDarkMode ? 'cursor-white.svg' : 'cursor.svg'}`}
      alt="Cursor"
      className={className}
    />
  );
};

export default CursorLogo;
