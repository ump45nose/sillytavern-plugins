import type { ComponentType } from "react";
import type { Data } from "../host/types";
export interface AddonHost {
  subscribe: (listener: () => void) => () => void;
  revision: () => number;
  snapshot: () => {
    chatKey: string;
    chatName: string;
    busy: boolean;
  };
  exportSnapshot: () => {
    key: string;
    timestamp: number;
    messages: {
      id: number;
      name: string;
      role: "user" | "assistant" | "system";
      text: string;
    }[];
  };
  download: (blob: Blob, filename: string) => void;
  jump: (id: number) => void;
  exportChat: (name: string) => Promise<void>;
}
export interface MessageTarget {
  chatKey: string;
  id: number;
  token: string;
  version: string;
}
export interface StoryReply {
  target: MessageTarget;
  type: string;
}
export interface TaskState {
  status: "idle" | "running" | "pausing" | "paused" | "error";
  label: string;
  error?: string;
}
export interface AddonRuntime {
  subscribe: (listener: () => void) => () => void;
  revision: () => number;
  state: () => Data;
  task: () => TaskState;
  action: (name: string, ...args: any[]) => Promise<any>;
  stop: () => void;
  dispose: () => void;
}
/** Only v2 add-ons receive their own metadata/config and explicitly granted host operations. */
export interface TaskHost extends AddonHost {
  metadata: () => Data;
  saveMetadata: (data: Data, chatKey: string) => Promise<void>;
  config: () => Data;
  saveConfig: (data: Data) => Promise<void>;
  onReply: (listener: (reply: StoryReply) => void) => () => void;
  onInput: (listener: () => void) => () => void;
  input: () => string;
  insert: (text: string, mode: "replace" | "caret") => void;
  write: (text: string | null, signal: AbortSignal, allowDraft?: boolean) => Promise<StoryReply>;
  target: (id: number) => MessageTarget;
  validTarget: (target: MessageTarget) => boolean;
  rewrite: (prompt: string, profile: string, signal: AbortSignal) => Promise<string>;
  profiles: () => {
    id: string;
    name: string;
  }[];
  saveImage: (dataUrl: string, signal: AbortSignal) => Promise<string>;
  attach: (target: MessageTarget, url: string, replace?: string) => Promise<boolean>;
  removeImage: (target: MessageTarget, url: string) => Promise<boolean>;
  request: (path: string, body: Data, signal: AbortSignal) => Promise<Response>;
  inputMode: (target: MessageTarget) => void;
  /** The current character's or group's other chats; `data` is this add-on's metadata when the listing carries it. */
  otherChats: () => Promise<{ name: string; data?: Data }[]>;
  /** This add-on's metadata in another chat of the current character or group. */
  chatMetadata: (name: string) => Promise<Data | undefined>;
  open: (view: "workspace" | "editor") => void;
  beforeClose: () => boolean;
}
export interface AddonViewProps {
  host: TaskHost;
  runtime: AddonRuntime;
  editor?: boolean;
}
export type AddonModule =
  | {
      apiVersion: 1;
      id: string;
      Workspace: ComponentType<{
        host: AddonHost;
      }>;
    }
  | {
      apiVersion: 2;
      id: string;
      Workspace: ComponentType<AddonViewProps>;
      Sidebar?: ComponentType<AddonViewProps>;
      createRuntime: (host: TaskHost) => AddonRuntime;
    };
export interface AddonManifest {
  id: string;
  apiVersion: 1 | 2;
  version: string;
  entry: string;
  css: string;
}
