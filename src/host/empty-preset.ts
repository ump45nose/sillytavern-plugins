import type { Data } from "./types";

/** Keep native markers: an empty prompts array makes SillyTavern restore its default instructions. */
export function emptyPreset(): Data {
  const markers = [
    ["worldInfoBefore", "世界书（前）"],
    ["personaDescription", "用户设定"],
    ["charDescription", "角色描述"],
    ["charPersonality", "角色性格"],
    ["scenario", "场景"],
    ["worldInfoAfter", "世界书（后）"],
    ["dialogueExamples", "对话示例"],
    ["chatHistory", "聊天记录"],
  ];
  const instructions = [
    ["main", "主提示词"],
    ["nsfw", "辅助提示词"],
    ["jailbreak", "历史后指令"],
    ["enhanceDefinitions", "补充角色设定"],
  ];
  return {
    temperature: 1,
    top_p: 1,
    top_k: 0,
    frequency_penalty: 0,
    presence_penalty: 0,
    repetition_penalty: 1,
    openai_max_context: 8192,
    openai_max_tokens: 1024,
    stream_openai: true,
    show_thoughts: true,
    impersonation_prompt: "",
    new_chat_prompt: "",
    new_group_chat_prompt: "",
    new_example_chat_prompt: "",
    continue_nudge_prompt: "",
    send_if_empty: "",
    wi_format: "{0}",
    scenario_format: "{{scenario}}",
    personality_format: "{{personality}}",
    prompts: [
      ...instructions.map(([identifier, name]) => ({
        identifier,
        name,
        role: "system",
        content: "",
        system_prompt: true,
      })),
      ...markers.map(([identifier, name]) => ({ identifier, name, marker: true, system_prompt: true })),
    ],
    prompt_order: [100000, 100001].map((character_id) => ({
      character_id,
      order: [
        "main",
        ...markers.map(([identifier]) => identifier),
        "nsfw",
        "jailbreak",
        "enhanceDefinitions",
      ].map((identifier) => ({ identifier, enabled: markers.some(([id]) => id === identifier) })),
    })),
  };
}
