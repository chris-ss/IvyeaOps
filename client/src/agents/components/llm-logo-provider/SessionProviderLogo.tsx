import type { LLMProvider } from '../../types/app';
import ClaudeLogo from './ClaudeLogo';
import CodexLogo from './CodexLogo';
import CursorLogo from './CursorLogo';
import GeminiLogo from './GeminiLogo';
import OpenCodeLogo from './OpenCodeLogo';
import HermesLogo from './HermesLogo';
import AgyLogo from './AgyLogo';

type SessionProviderLogoProps = {
  provider?: LLMProvider | string | null;
  className?: string;
};

export default function SessionProviderLogo({
  provider = 'claude',
  className = 'w-5 h-5',
}: SessionProviderLogoProps) {
  if (provider === 'cursor') {
    return <CursorLogo className={className} />;
  }

  if (provider === 'codex') {
    return <CodexLogo className={className} />;
  }

  if (provider === 'gemini') {
    return <GeminiLogo className={className} />;
  }

  if (provider === 'opencode') {
    return <OpenCodeLogo className={className} />;
  }

  if (provider === 'hermes') {
    return <HermesLogo className={className} />;
  }

  if (provider === 'agy') {
    return <AgyLogo className={className} />;
  }

  return <ClaudeLogo className={className} />;
}
