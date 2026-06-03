const GeminiLogo = ({className = 'w-5 h-5'}) => {
  return (
    <img src={`${import.meta.env.BASE_URL}icons/gemini-ai-icon.svg`} alt="Gemini" className={className} />
  );
};

export default GeminiLogo;