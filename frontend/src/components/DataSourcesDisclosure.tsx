import React, { useState } from 'react';
import { Icon } from './Icon';

interface DataSourcesDisclosureProps {
  category: 'hazards' | 'ecology';
  /** True when the analysis ran with fallback models - the listed live sources were not all actually used. */
  degraded?: boolean;
}

const HAZARD_SOURCES = [
  'BIS IS 1893:2016 Criteria for Earthquake Resistant Design of Structures',
  'USGS Earthquake Hazards Program 50-year seismic catalog',
  'Open-Meteo GloFAS & ECMWF ERA5 Hydrological Reanalysis Monitoring',
  'NDMA Vulnerability Atlas of India (flood & cyclone prone designations)',
];

const ECOLOGY_SOURCES = [
  'Copernicus Sentinel-2 L2A multispectral imagery via Element84 STAC',
  'SegFormer-B0 canopy segmentation & spectral index inference (NDVI/NDWI)',
  'National Green Tribunal (NGT) statutory lake & rajakaluve drainage buffers',
  'NBC 2016 / SP 41 passive solar & bioclimatic architecture principles',
  'Classical Mayamatam & Manasara Vastu Vidya spatial orientation canons',
];

export const DataSourcesDisclosure: React.FC<DataSourcesDisclosureProps> = ({ category, degraded = false }) => {
  const [isOpen, setIsOpen] = useState(false);
  const sources = category === 'hazards' ? HAZARD_SOURCES : ECOLOGY_SOURCES;

  return (
    <div className="bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-3.5 sm:p-4 text-[12px] text-[var(--text-3)] transition-ui">
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="w-full flex items-center justify-between gap-2 text-left cursor-pointer select-none group"
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="info" size={14} className="text-[var(--text-3)] group-hover:text-[var(--text-2)] transition-colors shrink-0" />
          <span className="font-medium text-[var(--text-2)] group-hover:text-[var(--text-1)] transition-colors">
            Data Sources & Standards
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-[11px] text-[var(--text-3)]">
            {sources.length} standards
          </span>
          <Icon
            name="chevron-down"
            size={13}
            className={`text-[var(--text-3)] transition-transform duration-250 ${
              isOpen ? 'rotate-180 text-[var(--text-1)]' : ''
            }`}
          />
        </div>
      </button>

      <div
        className={`grid transition-[grid-template-rows] duration-250 ease-out ${
          isOpen ? 'grid-rows-[1fr] mt-2.5 pt-2.5 border-t border-[var(--hairline)]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="overflow-hidden space-y-2">
          {degraded && (
            <div className="flex items-start gap-2 text-[12px] text-[var(--semantic-amber-ink)] leading-snug">
              <Icon name="alert-triangle" size={12} className="shrink-0 mt-0.5" />
              <span>
                Some telemetry services were unavailable during this analysis; deterministic
                fallback models were applied in place of the live sources listed below.
              </span>
            </div>
          )}
          {sources.map((src, idx) => (
            <div key={idx} className="flex items-start gap-2 text-[12px] text-[var(--text-3)] leading-snug">
              <Icon name="info" size={12} className="text-[var(--accent-ink)] shrink-0 mt-0.5" />
              <span>{src}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
