type IvyeaLogoProps = {
  className?: string;
};

// IvyeaAgent —— 自托管智能体，直接复用 IvyeaOps 站点主视觉（favicon.svg，明暗通用）。
const IvyeaLogo = ({ className = 'w-5 h-5' }: IvyeaLogoProps) => {
  return (
    <img
      src={`${import.meta.env.BASE_URL}favicon.svg`}
      alt="IvyeaAgent"
      className={className}
    />
  );
};

export default IvyeaLogo;
