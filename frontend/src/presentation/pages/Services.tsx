import React from "react";
import { ServiceManagementContainer } from "@presentation/containers/ServiceManagementContainer";

const ServicesPage: React.FC = () => {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
      <ServiceManagementContainer />
    </div>
  );
};

export default ServicesPage;
