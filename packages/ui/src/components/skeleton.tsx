import { cn } from "@pmagent/ui/lib/utils"

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("sk rounded-md", className)}
      {...props}
    />
  )
}

export { Skeleton }
