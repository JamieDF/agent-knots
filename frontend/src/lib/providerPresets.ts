/** Shared provider presets for the Setup Wizard and Settings' "Add
 * provider" dialog. Bare model ids only — every preset routes through
 * strands.models.openai.OpenAIModel (see session/manager.py), which
 * sends model_id as-is with no "provider/" prefix stripping. A
 * prefixed id 400s on "unknown model" (confirmed against a real
 * MiniMax call); kept in one place after that exact bug once existed
 * independently in two separate preset maps here. */
export const PROVIDER_PRESETS: Record<string, { model: string; base_url: string }> = {
  minimax: { model: 'minimax-m2.7', base_url: 'https://api.minimax.io/v1' },
  deepseek: { model: 'deepseek-chat', base_url: 'https://api.deepseek.com/v1' },
  openai: { model: 'gpt-4o-mini', base_url: '' },
  anthropic: { model: 'claude-sonnet-4-20250514', base_url: '' },
  ollama: { model: 'llama3', base_url: 'http://localhost:11434/v1' },
  custom: { model: '', base_url: '' },
}
