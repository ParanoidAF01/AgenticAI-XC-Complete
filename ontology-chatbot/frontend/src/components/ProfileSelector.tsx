import type { ProfileResponse } from '@/types/api';
import './ProfileSelector.css';

interface Props {
  profiles: ProfileResponse[];
  selected: string;
  onSelect: (name: string) => void;
}

export default function ProfileSelector({ profiles, selected, onSelect }: Props) {
  return (
    <div className="profile-selector">
      <select
        className="profile-select"
        value={selected}
        onChange={(e) => onSelect(e.target.value)}
      >
        <option value="" disabled>
          Select profile…
        </option>
        {profiles.map((p) => (
          <option key={p.name} value={p.name}>
            {p.name}
            {p.database_type ? ` (${p.database_type})` : ''}
          </option>
        ))}
      </select>
      <svg className="profile-select-icon" width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
        <path d="M3.5 5.5l3.5 3.5 3.5-3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </svg>
    </div>
  );
}
