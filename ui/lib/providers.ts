// Comprehensive provider database for Routism.
// Each provider has a known OpenAI-compatible base URL, a list of known/popular
// models (fallback if /v1/models fetch fails), and capability tags.

export interface ProviderInfo {
  id: string;
  name: string;
  baseUrl: string;
  docsUrl?: string;
  /** Override URL for fetching models (default: derived from baseUrl) */
  modelsUrl?: string;
  requiresKey: boolean;
  keyHint: string;
  knownModels: string[];
  tags: string[];
}

export const PROVIDERS: ProviderInfo[] = [
  // ── OpenAI / Direct ────────────────────────────────────────────────────
  {
    id: "openai",
    name: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    docsUrl: "https://platform.openai.com/api-keys",
    requiresKey: true,
    keyHint: "sk-... from platform.openai.com",
    knownModels: [
      "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
      "gpt-4.5-preview",
      "o3", "o3-mini", "o4-mini",
      "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
      "gpt-5.6-sol-pro", "gpt-5.6-terra-pro", "gpt-5.6-luna-pro",
      "gpt-5.5", "gpt-5.5-pro",
      "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo",
    ],
    tags: ["cloud", "code", "reasoning", "creative", "fast"],
  },
  {
    id: "anthropic",
    name: "Anthropic",
    baseUrl: "https://api.anthropic.com/v1",
    docsUrl: "https://console.anthropic.com/settings/keys",
    requiresKey: true,
    keyHint: "sk-ant-... from console.anthropic.com",
    knownModels: [
      "claude-sonnet-4-20250514", "claude-sonnet-4.8-20250514",
      "claude-sonnet-4", "claude-sonnet-4-6", "claude-sonnet-5",
      "claude-haiku-4-5",
      "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest",
      "claude-3-opus-latest", "claude-3-haiku-20240307",
      "claude-fable-5",
    ],
    tags: ["cloud", "code", "reasoning", "creative", "explain"],
  },
  {
    id: "google",
    name: "Google AI Studio",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai/",
    modelsUrl: "https://generativelanguage.googleapis.com/v1beta/models",
    docsUrl: "https://aistudio.google.com/apikey",
    requiresKey: true,
    keyHint: "AIza... from aistudio.google.com",
    knownModels: [
      "gemini-2.5-pro", "gemini-2.5-flash",
      "gemini-3.5-flash", "gemini-3.1-pro", "gemini-3-flash",
      "gemini-2.0-flash",
      "gemini-1.5-pro", "gemini-1.5-flash",
    ],
    tags: ["cloud", "code", "reasoning", "multimodal", "large_context"],
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    docsUrl: "https://platform.deepseek.com/api_keys",
    requiresKey: true,
    keyHint: "sk-... from platform.deepseek.com",
    knownModels: [
      "deepseek-chat", "deepseek-reasoner",
      "deepseek-coder", "deepseek-v3", "deepseek-r1",
      "deepseek-v4-flash", "deepseek-v4-pro",
    ],
    tags: ["cloud", "code", "reasoning", "math"],
  },

  // ── Aggregators / Multi-Model ──────────────────────────────────────────
  {
    id: "openrouter",
    name: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    docsUrl: "https://openrouter.ai/keys",
    requiresKey: true,
    keyHint: "sk-or-... from openrouter.ai/keys",
    knownModels: [
      "openai/gpt-4o", "openai/gpt-4o-mini",
      "openai/gpt-5.6-sol", "openai/gpt-5.6-terra", "openai/gpt-5.6-luna",
      "openai/gpt-5.6-sol-pro", "openai/gpt-5.6-terra-pro", "openai/gpt-5.6-luna-pro",
      "openai/o3", "openai/o3-mini", "openai/o4-mini",
      "anthropic/claude-sonnet-4", "anthropic/claude-sonnet-5",
      "anthropic/claude-sonnet-4-6", "anthropic/claude-3.5-sonnet",
      "anthropic/claude-haiku-4-5", "anthropic/claude-opus-4-8",
      "anthropic/claude-fable-5",
      "google/gemini-2.5-pro", "google/gemini-2.5-flash",
      "google/gemini-3.5-flash", "google/gemini-3.1-pro",
      "deepseek/deepseek-chat", "deepseek/deepseek-r1",
      "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro",
      "meta-llama/llama-3.3-70b-instruct", "meta-llama/llama-3.1-8b-instruct",
      "mistralai/mixtral-8x7b-instruct", "mistralai/mistral-large",
      "qwen/qwen-2.5-72b-instruct", "qwen/qwen3.7-max",
      "cohere/command-r-plus",
      "x-ai/grok-4.5", "x-ai/grok-build-0.1",
      "z-ai/glm-5.2", "minimax/minimax-m3",
    ],
    tags: ["cloud", "code", "reasoning", "creative", "fast"],
  },
  {
    id: "novita",
    name: "NovitaAI",
    baseUrl: "https://api.novita.ai/openai/v1",
    docsUrl: "https://novita.ai/settings/api-key",
    requiresKey: true,
    keyHint: "Novita API key from novita.ai",
    knownModels: [
      "meta-llama/llama-3.3-70b-instruct", "meta-llama/llama-3.1-8b-instruct",
      "mistralai/mixtral-8x7b-instruct-v0-1", "mistralai/mistral-large",
      "deepseek/deepseek-r1", "deepseek/deepseek-v3",
      "deepseek/deepseek-v4-flash",
      "qwen/qwen-2.5-72b-instruct", "qwen/qwen3-235b-a22b",
    ],
    tags: ["cloud", "code", "reasoning"],
  },
  {
    id: "huggingface",
    name: "Hugging Face Inference",
    baseUrl: "https://api-inference.huggingface.co/v1",
    docsUrl: "https://huggingface.co/settings/tokens",
    requiresKey: true,
    keyHint: "hf_... from huggingface.co/settings/tokens",
    knownModels: [
      "meta-llama/Llama-3.3-70B-Instruct", "meta-llama/Llama-3.1-8B-Instruct",
      "mistralai/Mixtral-8x7B-Instruct-v0.1",
      "Qwen/Qwen2.5-72B-Instruct", "microsoft/Phi-3-mini-4k-instruct",
    ],
    tags: ["cloud", "code", "reasoning"],
  },
  {
    id: "gmi-cloud",
    name: "GMI Cloud",
    baseUrl: "https://api.gmi-serving.com/v1",
    docsUrl: "https://gmi.cloud/dashboard",
    requiresKey: true,
    keyHint: "GMI Cloud API key",
    knownModels: [
      "deepseek-v3", "deepseek-r1",
      "deepseek-v4-flash", "deepseek-v4-pro",
      "meta-llama-3.1-70b-instruct", "meta-llama-3.1-8b-instruct",
      "qwen-2.5-72b-instruct", "qwen-2.5-32b-instruct",
    ],
    tags: ["cloud", "code", "reasoning"],
  },

  // ── Chinese / Regional Providers ───────────────────────────────────────
  {
    id: "zhipu",
    name: "Z.AI / GLM (Zhipu)",
    baseUrl: "https://api.z.ai/api/v1",
    docsUrl: "https://open.bigmodel.cn/usercenter/apikeys",
    requiresKey: true,
    keyHint: "Zhipu API key from open.bigmodel.cn",
    knownModels: [
      "glm-5p2", "glm-5.2", "glm-5.1", "glm-5", "glm-4.7",
      "glm-4-plus", "glm-4-flash", "glm-4-air",
    ],
    tags: ["cloud", "code", "reasoning"],
  },
  {
    id: "moonshot",
    name: "Kimi / Moonshot",
    baseUrl: "https://api.moonshot.ai/v1",
    docsUrl: "https://platform.moonshot.cn/console/api-keys",
    requiresKey: true,
    keyHint: "Moonshot API key",
    knownModels: [
      "kimi-k2.7-code", "kimi-k2.7-code-highspeed",
      "kimi-k2.6", "kimi-k2.5",
    ],
    tags: ["cloud", "code", "reasoning"],
  },
  {
    id: "stepfun",
    name: "StepFun Step Plan",
    baseUrl: "https://api.stepfun.ai/step_plan/v1",
    docsUrl: "https://platform.stepfun.ai/api-keys",
    requiresKey: true,
    keyHint: "StepFun API key",
    knownModels: [
      "step-3.7-flash", "step-3.5-flash",
      "step-3-flash", "step-2-flash",
    ],
    tags: ["cloud", "code", "reasoning"],
  },
  {
    id: "minimax",
    name: "MiniMax",
    baseUrl: "https://api.minimax.io/v1",
    docsUrl: "https://platform.minimax.io/api-keys",
    requiresKey: true,
    keyHint: "MiniMax API key",
    knownModels: [
      "MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed",
      "MiniMax-M2.5", "MiniMax-M2.5-highspeed",
    ],
    tags: ["cloud", "code", "reasoning"],
  },

  // ── Chinese Cloud / DashScope ──────────────────────────────────────────
  {
    id: "dashscope",
    name: "Qwen Cloud / DashScope",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    docsUrl: "https://help.aliyun.com/document_detail/2712195.html",
    requiresKey: true,
    keyHint: "sk-... from dashscope.aliyuncs.com",
    knownModels: [
      "qwen-plus", "qwen-max", "qwen-turbo", "qwen-long",
      "qwen-vl-plus", "qwen-vl-max",
      "qwen3-coder-plus", "qwen3-coder-next",
      "qwen3.5-plus", "qwen3.6-plus", "qwen3.7-plus",
      "qwen3-max-2026-01-23",
    ],
    tags: ["cloud", "code", "reasoning", "multimodal"],
  },
  {
    id: "alibaba-coding-plan",
    name: "Alibaba Cloud Coding Plan",
    baseUrl: "https://coding-intl.dashscope.aliyuncs.com/v1",
    docsUrl: "https://www.aliyun.com/product/coding-plan",
    requiresKey: true,
    keyHint: "Coding Plan API key",
    knownModels: [
      "qwen3-coder-plus", "qwen3-coder-next",
      "qwen3.5-plus", "qwen3.6-plus", "qwen3.7-plus",
      "qwen3-max-2026-01-23",
      "qwen-max", "qwen-plus",
    ],
    tags: ["cloud", "code", "reasoning"],
  },

  // ── Xiaomi, Tencent ────────────────────────────────────────────────────
  {
    id: "xiaomi-mimo",
    name: "Xiaomi MiMo",
    baseUrl: "https://api.xiaomimimo.com/v1",
    docsUrl: "https://xiaomimimo.com/docs",
    requiresKey: true,
    keyHint: "MiMo API key",
    knownModels: [
      "mimo-v2.5-pro", "mimo-v2.5-pro-ultraspeed",
      "mimo-v2.5", "mimo-v2.5-omni", "mimo-v2.5-flash",
      "mimo-v2.5-free",
    ],
    tags: ["cloud", "code", "reasoning", "creative"],
  },
  {
    id: "tencent-hunyuan",
    name: "Tencent TokenHub (Hunyuan)",
    baseUrl: "https://api.hunyuan.tencent.com/v1",
    docsUrl: "https://console.cloud.tencent.com/hunyuan",
    requiresKey: true,
    keyHint: "Tencent Hunyuan API key",
    knownModels: [
      "hy3", "hy3-preview", "hy3-free",
      "hunyuan-turbo", "hunyuan-standard",
    ],
    tags: ["cloud", "code", "reasoning"],
  },

  // ── GPU Cloud / NIM ────────────────────────────────────────────────────
  {
    id: "nvidia-nim",
    name: "NVIDIA NIM",
    baseUrl: "https://integrate.api.nvidia.com/v1",
    docsUrl: "https://build.nvidia.com/explore/discover",
    requiresKey: true,
    keyHint: "nvapi-... from build.nvidia.com",
    knownModels: [
      "nvidia/llama-3.3-nemotron-super-49b-v1", "nvidia/llama-3.3-nemotron-super-49b-v1.5",
      "nvidia/llama-3.1-nemotron-70b-instruct", "nvidia/llama-3.1-nemotron-51b-instruct",
      "nvidia/llama-3.1-nemotron-nano-8b-v1",
      "nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3-super-120b-a12b",
      "nvidia/nemotron-3-nano-30b-a3b",
      "nvidia/nemotron-4-340b-instruct",
      "meta/llama-3.3-70b-instruct", "meta/llama-3.1-70b-instruct", "meta/llama-3.1-8b-instruct",
      "meta/llama-3.2-11b-vision-instruct", "meta/llama-3.2-90b-vision-instruct",
      "meta/llama-4-maverick-17b-128e-instruct",
      "mistralai/mixtral-8x22b-instruct-v0.1", "mistralai/mixtral-8x7b-instruct-v0.1",
      "mistralai/mistral-large", "mistralai/mistral-large-3-675b-instruct-2512",
      "mistralai/mistral-small-4-119b-2603",
      "deepseek-ai/deepseek-v4-flash", "deepseek-ai/deepseek-v4-pro",
      "deepseek-ai/deepseek-coder-6.7b-instruct",
      "google/gemma-3-12b-it", "google/gemma-3-4b-it", "google/gemma-4-31b-it",
      "qwen/qwen3-next-80b-a3b-instruct", "qwen/qwen3.5-122b-a10b",
      "microsoft/phi-4-mini-instruct", "microsoft/phi-4-multimodal-instruct",
      "stepfun-ai/step-3.5-flash", "stepfun-ai/step-3.7-flash",
      "z-ai/glm-5.2",
    ],
    tags: ["cloud", "code", "reasoning"],
  },
  {
    id: "arcee",
    name: "Arcee AI",
    baseUrl: "https://api.arcee.ai/v1",
    docsUrl: "https://arcee.ai/api-keys",
    requiresKey: true,
    keyHint: "Arcee API key",
    knownModels: [
      "trinity-mini", "trinity-large-preview",
      "arcee-3.0",
    ],
    tags: ["cloud", "code", "reasoning"],
  },

  // ── Enterprise Cloud ───────────────────────────────────────────────────
  {
    id: "aws-bedrock",
    name: "AWS Bedrock",
    baseUrl: "https://bedrock-runtime.us-east-1.amazonaws.com/v1",
    docsUrl: "https://docs.aws.amazon.com/bedrock/latest/userguide/api-setup.html",
    requiresKey: true,
    keyHint: "AWS IAM access key (or API key for cross-region)",
    knownModels: [
      "anthropic.claude-sonnet-4-20250514", "anthropic.claude-3-5-sonnet-20241022",
      "anthropic.claude-3-5-haiku-20241022", "anthropic.claude-3-opus-20240229",
      "meta.llama3-3-70b-instruct-v1:0", "meta.llama3-1-8b-instruct-v1:0",
      "amazon.nova-pro-v1:0", "amazon.nova-lite-v1:0", "amazon.nova-micro-v1:0",
      "deepseek.r1-v1:0", "mistral.mixtral-8x7b-instruct-v0:1",
      "mistral.mistral-large-2407-v1:0",
      "cohere.command-r-v1:0",
    ],
    tags: ["cloud", "code", "reasoning", "large_context"],
  },
  {
    id: "azure-foundry",
    name: "Azure Foundry",
    baseUrl: "https://YOUR-ENDPOINT.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT",
    docsUrl: "https://oai.azure.com/portal",
    requiresKey: true,
    keyHint: "Azure AI endpoint + API key from oai.azure.com",
    knownModels: [
      "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
      "gpt-4", "gpt-3.5-turbo",
      "o3-mini", "o4-mini",
    ],
    tags: ["cloud", "code", "reasoning"],
  },

  // ── Free / Community ────────────────────────────────────────────────────
  {
    id: "groq",
    name: "Groq",
    baseUrl: "https://api.groq.com/openai/v1",
    docsUrl: "https://console.groq.com/keys",
    requiresKey: true,
    keyHint: "gsk_... from console.groq.com/keys",
    knownModels: [
      "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
      "llama-3.2-3b-preview", "llama-3.2-90b-vision-preview",
      "qwen-qwq-32b", "mixtral-8x7b-32768", "gemma2-9b-it",
      "gemma-7b-it", "deepseek-r1-distill-llama-70b",
      "distil-whisper-large-v3-en",
    ],
    tags: ["cloud", "code", "reasoning", "math", "creative", "fast", "large_context", "free"],
  },
  {
    id: "github-copilot",
    name: "GitHub Copilot",
    baseUrl: "https://models.inference.ai.azure.com",
    modelsUrl: "https://models.inference.ai.azure.com/models",
    docsUrl: "https://github.com/settings/tokens",
    requiresKey: true,
    keyHint: "GitHub personal access token (classic, with read:org)",
    knownModels: [
      "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
      "o3-mini", "o4-mini",
      "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
      "anthropic/claude-sonnet-4", "anthropic/claude-sonnet-5",
      "meta-llama/Llama-3.3-70B-Instruct", "meta-llama/Llama-3.1-8B-Instruct",
      "google/gemini-2.5-flash-001", "google/gemini-2.5-pro",
      "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro",
      "mistralai/mistral-large", "microsoft/phi-4-multimodal-instruct",
      "qwen/qwen3.7-max",
    ],
    tags: ["cloud", "code", "reasoning", "free"],
  },
  {
    id: "huggingface-free",
    name: "Hugging Face (Free)",
    baseUrl: "https://api-inference.huggingface.co/v1",
    docsUrl: "https://huggingface.co/settings/tokens",
    requiresKey: true,
    keyHint: "hf_... (free tier available)",
    knownModels: [
      "meta-llama/Llama-3.3-70B-Instruct",
      "microsoft/Phi-3-mini-4k-instruct",
      "HuggingFaceH4/zephyr-7b-beta",
    ],
    tags: ["cloud", "code", "reasoning", "free"],
  },

  // ── Local ──────────────────────────────────────────────────────────────
  // Prefer the one-click cards on the Providers page; these entries remain for
  // the manual provider dropdown / custom path.
  {
    id: "lm-studio",
    name: "LM Studio",
    baseUrl: "http://localhost:1234/v1",
    docsUrl: "https://lmstudio.ai/docs",
    requiresKey: false,
    keyHint: "Not needed (local)",
    knownModels: [],  // user's own local models
    tags: ["local", "free"],
  },
  {
    id: "mlx",
    name: "MLX / oMLX (Local)",
    baseUrl: "http://localhost:6969/v1",
    docsUrl: "https://github.com/ml-explore/mlx-lm",
    requiresKey: false,
    keyHint: "Optional — only if your local server requires auth",
    knownModels: [],
    tags: ["local", "free", "fast"],
  },
  {
    id: "ollama",
    name: "Ollama (Local)",
    baseUrl: "http://localhost:11434/v1",
    docsUrl: "https://ollama.com/download",
    requiresKey: false,
    keyHint: "Not needed (local)",
    knownModels: [
      "qwen3:1.7b", "qwen3:4b", "qwen2.5:7b", "qwen2.5:0.5b",
      "llama3.2:3b", "llama3.2:1b", "llama3.1:8b", "llama3.3:70b",
      "deepseek-r1:7b", "deepseek-r1:1.5b", "mistral:7b",
      "gemma3:4b", "gemma3:12b",
      "nomic-embed-text:v1.5", "mxbai-embed-large:v1",
    ],
    tags: ["local", "free", "fast"],
  },

  // ── Cloud Community Models ─────────────────────────────────────────────
  {
    id: "fireworks",
    name: "Fireworks AI",
    baseUrl: "https://api.fireworks.ai/inference/v1",
    docsUrl: "https://fireworks.ai/api-keys",
    requiresKey: true,
    keyHint: "fw_... from fireworks.ai/account/api-keys",
    knownModels: [
      "accounts/fireworks/models/llama-v3p3-70b-instruct",
      "accounts/fireworks/models/llama-v3p1-8b-instruct",
      "accounts/fireworks/models/qwen2p5-coder-32b-instruct",
      "accounts/fireworks/models/mixtral-8x7b-instruct",
      "accounts/fireworks/models/deepseek-r1",
      "accounts/fireworks/models/deepseek-v4-flash",
      "accounts/fireworks/models/gemma3-27b-it",
      "accounts/fireworks/models/phi-4-mini-instruct",
    ],
    tags: ["cloud", "code", "reasoning", "fast"],
  },
  {
    id: "together",
    name: "Together AI",
    baseUrl: "https://api.together.xyz/v1",
    docsUrl: "https://api.together.xyz/settings/api-keys",
    requiresKey: true,
    keyHint: "tgp_... from together.xyz",
    knownModels: [
      "meta-llama/Llama-3.3-70B-Instruct-Turbo",
      "meta-llama/Llama-3.1-8B-Instruct-Turbo",
      "mistralai/Mixtral-8x22B-Instruct-v0.1",
      "deepseek-ai/DeepSeek-R1", "deepseek-ai/deepseek-v4-flash",
      "Qwen/Qwen2.5-72B-Instruct-Turbo", "Qwen/Qwen3-235B-A22B-Turbo",
      "google/gemma-3-12b-it", "google/gemma-2-27b-it",
      "microsoft/phi-4-mini-instruct",
    ],
    tags: ["cloud", "code", "reasoning", "free"],
  },
  {
    id: "ollama-cloud",
    name: "Ollama Cloud",
    baseUrl: "https://api.ollama.com/v1",
    docsUrl: "https://ollama.com/cloud",
    requiresKey: true,
    keyHint: "ollama API key",
    knownModels: [
      "llama3.3:70b", "llama3.1:8b", "qwen2.5:72b",
      "qwen3.5:397b", "qwen3-coder:480b", "qwen3-coder-next",
      "deepseek-r1:70b", "deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v3.2",
      "mistral:7b", "mistral-large-3:675b", "ministral-3:8b",
      "gemma3:12b", "gemma3:27b", "gemma4:31b",
      "glm-4.7", "glm-5", "glm-5.1", "glm-5.2",
      "kimi-k2.5", "kimi-k2.6", "kimi-k2.7-code",
      "minimax-m2.5", "minimax-m2.7", "minimax-m3",
      "nemotron-3-nano:30b", "nemotron-3-super", "nemotron-3-ultra",
      "gemini-3-flash-preview",
      "gpt-oss:20b", "gpt-oss:120b",
    ],
    tags: ["cloud", "code", "reasoning", "free"],
  },

  // ── Developer Tools / Gateways ──────────────────────────────────────────
  {
    id: "opencode",
    name: "OpenCode",
    // OpenAI-compatible root only (never …/chat/completions — that breaks health probes)
    baseUrl: "https://opencode.ai/zen/v1",
    modelsUrl: "https://opencode.ai/zen/v1/models",
    docsUrl: "https://opencode.ai",
    requiresKey: true,
    keyHint: "OC_... from opencode.ai",
    knownModels: [
      "deepseek-v4-flash", "deepseek-v4-flash-free", "deepseek-v4-pro",
      "gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.5", "gpt-5.5-pro",
      "claude-sonnet-4", "claude-sonnet-4-6", "claude-haiku-4-5",
      "gemini-3.5-flash", "gemini-3.1-pro",
      "kimi-k2.7-code", "kimi-k2.6",
      "nemotron-3-ultra-free", "qwen3.6-plus",
      "mimo-v2.5-free", "hy3-free", "north-mini-code-free",
    ],
    tags: ["cloud", "code", "reasoning", "free"],
  },
  {
    id: "kilo",
    name: "Kilo Code",
    baseUrl: "https://api.kilo.ai/api/gateway",
    modelsUrl: "https://api.kilo.ai/api/gateway/models",
    docsUrl: "https://kilo.ai",
    requiresKey: true,
    keyHint: "Kilo API key",
    knownModels: [
      "kilo-auto/free", "kilo-auto/pro", "kilo-auto/frontier",
      "kilo-auto/balanced", "kilo-auto/efficient", "kilo-auto/small",
      "anthropic/claude-sonnet-5", "anthropic/claude-fable-5",
      "openai/gpt-5.6-sol", "openai/gpt-5.6-terra", "openai/gpt-5.6-luna",
      "deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash",
      "google/gemini-3.5-flash",
      "minimax/minimax-m3", "moonshotai/kimi-k2.7-code",
      "nvidia/nemotron-3-ultra-550b-a55b",
      "qwen/qwen3.7-max", "x-ai/grok-build-0.1", "z-ai/glm-5.2",
    ],
    tags: ["cloud", "code", "reasoning", "free"],
  },

  // ── xAI ─────────────────────────────────────────────────────────────────
  {
    id: "xai",
    name: "xAI Grok",
    baseUrl: "https://api.x.ai/v1",
    docsUrl: "https://x.ai/api",
    requiresKey: true,
    keyHint: "xai-... from x.ai",
    knownModels: [
      "grok-3", "grok-3-mini", "grok-2", "grok-2-mini",
      "grok-4.5", "grok-build-0.1",
    ],
    tags: ["cloud", "code", "reasoning"],
  },
];

// Providers that truly can't list models via a REST endpoint.
// For all others, the "Fetch models" button calls /v1/models (or modelsUrl).
export const NO_FETCH_PROVIDERS = new Set([
  "aws-bedrock",      // IAM-based auth, not a simple /v1/models endpoint
  "azure-foundry",     // user's own deployment URL, no standard model list
  // Local one-click providers use /v1/management/local/* discover instead of
  // the cloud fetch-models path (still fetchable via custom form if desired).
  "lm-studio",
  "mlx",
  "ollama",
  "huggingface",       // custom REST API, not OpenAI-compatible /v1/models
  "huggingface-free",  // same
  "tencent-hunyuan",   // /v1/models returns 404, no standard models endpoint
]);

// Sort: local + free first, then alphabetically
export function sortedProviders(): ProviderInfo[] {
  return [...PROVIDERS].sort((a, b) => {
    const aScore = (a.tags.includes("local") ? 0 : a.tags.includes("free") ? 1 : 2);
    const bScore = (b.tags.includes("local") ? 0 : b.tags.includes("free") ? 1 : 2);
    if (aScore !== bScore) return aScore - bScore;
    return a.name.localeCompare(b.name);
  });
}
