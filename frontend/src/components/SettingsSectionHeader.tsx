import { Icon } from "./Icon";

type SettingsSectionHeaderProps = {
  description: string;
  icon: "spark" | "shield" | "rocket" | "settings";
  title: string;
};

export function SettingsSectionHeader(
  { icon, title, description }: SettingsSectionHeaderProps,
): JSX.Element {
  return (
    <div className="settings-section-header">
      <div className="settings-section-icon">
        <Icon name={icon} className="icon-sm" />
      </div>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </div>
  );
}
