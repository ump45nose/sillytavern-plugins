import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { Ellipsis } from "./icons";
import { Popover } from "./Popover";
import { MessageActionButton } from "./MessageActionButton";

/** Secondary RP tools keep their desktop positions and become labelled rows on a phone. */
export function RPToolMenu({ mobile, children }: { mobile: boolean; children: ReactNode }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  useEffect(() => setAnchor(null), [mobile]);
  if (!mobile) return <>{children}</>;
  return (
    <>
      <button
        className="wb-rp-tool"
        aria-label="更多对白操作"
        title="更多对白操作"
        aria-expanded={!!anchor}
        onClick={(event) => setAnchor(anchor ? null : event.currentTarget)}
      >
        <Ellipsis size={20} />
      </button>
      {anchor && (
        <Popover
          anchor={anchor}
          title="对白操作"
          className="wb-message-menu wb-rp-more"
          onClose={() => setAnchor(null)}
        >
          <div
            className="wb-message-menu-rows"
            onClick={(event) => {
              if ((event.target as Element).closest("button")) setAnchor(null);
            }}
          >
            {Children.map(children, (child) => {
              if (!isValidElement<ButtonHTMLAttributes<HTMLButtonElement> & { iconOnly?: boolean }>(child))
                return child;
              if (child.type === MessageActionButton)
                return cloneElement(child, { className: undefined, iconOnly: false });
              if (child.type !== "button") return null;
              return cloneElement(
                child,
                { className: undefined },
                <>
                  {child.props.children}
                  <span>{child.props["aria-label"] || child.props.title}</span>
                </>,
              );
            })}
          </div>
        </Popover>
      )}
    </>
  );
}
