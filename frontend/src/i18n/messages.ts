import { enMessages } from "./messages.en";
import { zhMessages } from "./messages.zh";

export type Language = "zh-CN" | "en-US";

export type MessageDictionary = Record<string, string>;

export const DEFAULT_LANGUAGE: Language = "en-US";
export const LANGUAGE_STORAGE_KEY = "openbot_language";
export const SUPPORTED_LANGUAGES: Language[] = ["zh-CN", "en-US"];

export const messages: Record<Language, MessageDictionary> = {
  "en-US": enMessages,
  "zh-CN": zhMessages,
};
