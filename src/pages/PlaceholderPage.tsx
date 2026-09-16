import type { LucideIcon } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

interface PlaceholderPageProps {
  title: string;
  description: string;
  icon: LucideIcon;
  specNote: string;
}

/** Página de marcador de posición para módulos que se implementarán en SPECs siguientes. */
export function PlaceholderPage({
  title,
  description,
  icon: Icon,
  specNote,
}: PlaceholderPageProps) {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <Card glass>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div
              className="bg-accent-indigo/15 flex h-10 w-10 items-center justify-center rounded-lg text-accent-indigo-strong"
              aria-hidden
            >
              <Icon className="h-5 w-5" />
            </div>
            <CardTitle>{title}</CardTitle>
          </div>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent>
          <p>{specNote}</p>
        </CardContent>
      </Card>
    </div>
  );
}
