import React from "react";
import { cn } from "@shared/utils/cn";

interface SkeuoCardProps {
  borderColor?: "blue" | "orange" | "green" | "yellow" | "purple" | "red";
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
  hoverable?: boolean;
}

const borderColorMap = {
  blue: "border-blue-500 bg-blue-50/20",
  orange: "border-orange-500 bg-orange-50/20",
  green: "border-emerald-500 bg-emerald-50/20",
  yellow: "border-amber-500 bg-amber-50/20",
  purple: "border-purple-500 bg-purple-50/20",
  red: "border-red-500 bg-red-50/20",
};

export const SkeuoCard: React.FC<SkeuoCardProps> = ({
  borderColor = "blue",
  children,
  className,
  onClick,
  hoverable = true,
}) => {
  return (
    <div
      onClick={onClick}
      className={cn(
        "rounded-lg bg-white border-l-[5px] p-6",
        borderColorMap[borderColor],
        "shadow-[0_2px_8px_rgba(0,0,0,0.08)]",
        "transition-all duration-200",
        hoverable && "hover:shadow-[0_4px_12px_rgba(0,0,0,0.12)] hover:scale-[1.01] active:scale-[0.99]",
        onClick && "cursor-pointer",
        className
      )}
    >
      {children}
    </div>
  );
};

export const SkeuoCardHeader: React.FC<{
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}> = ({ icon, title, subtitle, actions }) => (
  <div className="flex items-start justify-between gap-4 mb-4">
    <div className="flex items-center gap-3">
      <div className="p-2.5 bg-white rounded-lg shadow-inner border border-gray-100 text-gray-700">
        {icon}
      </div>
      <div>
        <h3 className="font-bold text-gray-800 text-base uppercase tracking-tight">
          {title}
        </h3>
        {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
      </div>
    </div>
    {actions && <div className="flex gap-2">{actions}</div>}
  </div>
);

export const SkeuoCardFooter: React.FC<{
  left?: React.ReactNode;
  right?: React.ReactNode;
  divider?: boolean;
}> = ({ left, right, divider = true }) => (
  <div className={cn(divider && "border-t border-gray-100 pt-4 mt-4")}>
    <div className="flex items-center justify-between text-xs text-gray-500">
      <div className="flex items-center gap-2">{left}</div>
      <div className="font-bold text-gray-700">{right}</div>
    </div>
  </div>
);
