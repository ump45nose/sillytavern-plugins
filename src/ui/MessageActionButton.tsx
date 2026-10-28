import type { ButtonHTMLAttributes } from "react";
import {
  invokeMessageAction,
  messageActionDisabled,
  messageActions,
  messageControl,
  type MessageAction,
} from "./message-actions";

export function MessageActionButton({
  node,
  action,
  busy = false,
  iconOnly = false,
  onInvoke,
  size = 17,
  children,
  ...props
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onClick"> & {
  node: HTMLElement | null | undefined;
  action: MessageAction;
  busy?: boolean;
  iconOnly?: boolean;
  size?: number;
  onInvoke?: () => void;
}) {
  const [Icon, label] = messageActions[action];
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      {...props}
      disabled={props.disabled || messageActionDisabled(messageControl(node, action), busy)}
      onClick={() => {
        onInvoke?.();
        invokeMessageAction(node, action);
      }}
    >
      <Icon size={size} />
      {!iconOnly && (children ?? <span>{label}</span>)}
    </button>
  );
}
