import { Mic } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface VoiceEnableModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function VoiceEnableModal({ open, onClose, onConfirm }: VoiceEnableModalProps) {
  return (
    <Dialog open={open} onOpenChange={(value) => (value ? null : onClose())}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Mic className="h-5 w-5 text-teal-700" />
            Turn on voice mode?
          </DialogTitle>
          <DialogDescription className="space-y-2 text-sm">
            <span>
              Mira will use your microphone to listen continuously on this page, and will speak responses out
              loud. You can interrupt her at any time by talking.
            </span>
            <span className="block rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-amber-900">
              Remember to click <strong>Voice off</strong> when you're done — the mic stays on until you turn it off.
            </span>
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" onClick={onConfirm} className="bg-teal-700 hover:bg-teal-600">
            <Mic className="mr-2 h-4 w-4" />
            Turn on voice
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
