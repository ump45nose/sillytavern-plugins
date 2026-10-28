import type { Panel } from "../../host/types";
export type MobileSheet = "management" | "tools" | "options" | HTMLElement | null;
export interface MobileState {
  left: boolean;
  panel: Panel;
  editor: boolean;
  sheet: MobileSheet;
}
export const interactive = "button,input,textarea,select,a,[contenteditable=true],iframe,video";
