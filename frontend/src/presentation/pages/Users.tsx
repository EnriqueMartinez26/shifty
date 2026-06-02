import React from "react";
import { UserManagementContainer } from "@presentation/containers/UserManagementContainer";

const UsersPage: React.FC = () => {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
      <UserManagementContainer />
    </div>
  );
};

export default UsersPage;
