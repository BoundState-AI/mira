import { Bot } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button, type ButtonProps } from "@/components/ui/button";
import {
  buildChatScopeSearch,
  persistModuleChatLaunchState,
  type MiraModuleChatLaunchState,
} from "@/lib/mira-chat-context";

interface ModuleChatButtonProps extends Omit<ButtonProps, "onClick"> {
  launchState: MiraModuleChatLaunchState;
  label?: string;
}

export function ModuleChatButton({
  launchState,
  label = "Ask MIRA About This Page",
  variant = "outline",
  size = "sm",
  ...buttonProps
}: ModuleChatButtonProps) {
  const navigate = useNavigate();

  return (
    <Button
      {...buttonProps}
      variant={variant}
      size={size}
      onClick={() => {
        persistModuleChatLaunchState(launchState);
        navigate(
          {
            pathname: "/chat",
            search: buildChatScopeSearch(launchState.scopeKey),
          },
          { state: launchState },
        );
      }}
    >
      <Bot className="h-4 w-4" />
      {label}
    </Button>
  );
}
