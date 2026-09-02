import React, { createContext, useContext, useMemo, useState } from "react";

export interface DesignContextValue {
  designName: string;
  freqGhz: number;
  dipoleLengthM: number;
  solver: string;
  resonanceGhz: number;
  minS11Db: number;
  solverMode: string | null;
  solverAnchorMode: string | null;
}

interface DesignContextState {
  designContext: DesignContextValue | null;
  setDesignContext: React.Dispatch<React.SetStateAction<DesignContextValue | null>>;
}

const DesignContext = createContext<DesignContextState | null>(null);

export const DesignContextProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [designContext, setDesignContext] = useState<DesignContextValue | null>(null);
  const value = useMemo(() => ({ designContext, setDesignContext }), [designContext]);

  return <DesignContext.Provider value={value}>{children}</DesignContext.Provider>;
};

export function useDesignContext(): DesignContextState {
  const context = useContext(DesignContext);
  if (!context) throw new Error("useDesignContext must be used inside <DesignContextProvider>");
  return context;
}
