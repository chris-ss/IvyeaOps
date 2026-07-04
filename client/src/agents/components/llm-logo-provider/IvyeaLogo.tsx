type IvyeaLogoProps = {
  className?: string;
};

// IvyeaAgent —— 自托管智能体，用品牌 logo（绿色 Y+叶子，白底方形，明暗通用）。
const IvyeaLogo = ({ className = 'w-5 h-5' }: IvyeaLogoProps) => {
  return (
    <img
      src={`${import.meta.env.BASE_URL}ivyea-logo.png`}
      alt="IvyeaAgent"
      className={className}
    />
  );
};

export default IvyeaLogo;
