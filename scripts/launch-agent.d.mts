export function buildLaunchAgentPlist(options: {
  nodePath: string;
  scriptPath: string;
  workingDirectory: string;
  stdoutPath: string;
  stderrPath: string;
  env: Record<string, string | undefined>;
  pathValue: string;
}): string;

export function main(command?: string): void;
