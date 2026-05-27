terraform {
  required_version = ">= 1.8.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
}

locals {
  project_name = "sc-demo-arch"
  location     = "australiaeast"
}

# 1. Resource group
resource "azurerm_resource_group" "rg" {
  name     = "${local.project_name}-rg"
  location = local.location
}

# 2. Virtual network
# 3. App subnet
# 4. DB subnet
resource "azurerm_virtual_network" "vnet" {
  name                = "${local.project_name}-vnet"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = ["10.10.0.0/16"]
}

resource "azurerm_subnet" "subnet_app" {
  name                 = "${local.project_name}-snet-app"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.10.1.0/24"]
}

resource "azurerm_subnet" "subnet_db" {
  name                 = "${local.project_name}-snet-db"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.10.2.0/24"]
}

# 5. NSG for app subnet
# 6. NSG rule for HTTP
resource "azurerm_network_security_group" "nsg_app" {
  name                = "${local.project_name}-nsg-app"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name

  security_rule {
    name                       = "allow-http-inbound"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

# 7. NSG for db subnet
# 8. NSG rule for SQL from app subnet
resource "azurerm_network_security_group" "nsg_db" {
  name                = "${local.project_name}-nsg-db"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name

  security_rule {
    name                       = "allow-sql-from-app"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "1433"
    source_address_prefixes    = ["10.10.1.0/24"]
    destination_address_prefix = "*"
  }
}

# 9. NSG associations
resource "azurerm_subnet_network_security_group_association" "app_assoc" {
  subnet_id                 = azurerm_subnet.subnet_app.id
  network_security_group_id = azurerm_network_security_group.nsg_app.id
}

resource "azurerm_subnet_network_security_group_association" "db_assoc" {
  subnet_id                 = azurerm_subnet.subnet_db.id
  network_security_group_id = azurerm_network_security_group.nsg_db.id
}

# 10. Public IP for VM
resource "azurerm_public_ip" "vm_pip" {
  name                = "${local.project_name}-vm-pip"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

# 11. NIC for VM
resource "azurerm_network_interface" "vm_nic" {
  name                = "${local.project_name}-vm-nic"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name

  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.subnet_app.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.vm_pip.id
  }
}

# 12. Linux VM
resource "azurerm_linux_virtual_machine" "vm" {
  name                = "${local.project_name}-vm01"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  size                = "Standard_B2s"
  admin_username      = "azureuser"

  network_interface_ids = [
    azurerm_network_interface.vm_nic.id
  ]

  admin_ssh_key {
    username   = "azureuser"
    public_key = "ssh-rsa REPLACE_WITH_YOUR_PUBLIC_KEY"
  }

  os_disk {
    name                 = "${local.project_name}-vm01-osdisk"
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }
}

# 13. Storage account
resource "azurerm_storage_account" "sa" {
  name                     = "scdemoarchstorage01" # must be globally unique, change if needed
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  allow_blob_public_access = false
}

# 14. Key Vault
resource "azurerm_key_vault" "kv" {
  name                        = "sc-demo-arch-kv01"
  location                    = azurerm_resource_group.rg.location
  resource_group_name         = azurerm_resource_group.rg.name
  tenant_id                   = "00000000-0000-0000-0000-000000000000" # replace with your tenant
  sku_name                    = "standard"
  purge_protection_enabled    = false
  soft_delete_retention_days  = 7

  access_policy {
    tenant_id = "00000000-0000-0000-0000-000000000000" # replace
    object_id = "00000000-0000-0000-0000-000000000000" # replace (user or SPN)
    secret_permissions = [
      "Get",
      "Set",
      "List"
    ]
  }
}

# 15. App Service plan
resource "azurerm_service_plan" "appplan" {
  name                = "${local.project_name}-asp"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  os_type             = "Linux"
  sku_name            = "P1v3"
}

# 16. Web App
resource "azurerm_linux_web_app" "webapp" {
  name                = "${local.project_name}-webapp"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  service_plan_id     = azurerm_service_plan.appplan.id

  site_config {
    linux_fx_version = "PYTHON|3.11"
  }

  app_settings = {
    "WEBSITE_RUN_FROM_PACKAGE" = "0"
  }
}

# 17. SQL Server
# 18. SQL Database
resource "azurerm_mssql_server" "sql" {
  name                         = "${local.project_name}-sqlsrv"
  resource_group_name          = azurerm_resource_group.rg.name
  location                     = azurerm_resource_group.rg.location
  version                      = "12.0"
  administrator_login          = "sqladminuser"
  administrator_login_password = "ChangeM3Now!" # demo only, replace or use Key Vault
}

resource "azurerm_mssql_database" "sqldb" {
  name           = "${local.project_name}-sqldb"
  server_id      = azurerm_mssql_server.sql.id
  sku_name       = "GP_S_Gen5_2"
  max_size_gb    = 32
}

# 19. Log Analytics workspace
resource "azurerm_log_analytics_workspace" "law" {
  name                = "${local.project_name}-law"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

# 20. Application Insights
resource "azurerm_application_insights" "appi" {
  name                = "${local.project_name}-appi"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.law.id
}

output "resource_group_name" {
  value = azurerm_resource_group.rg.name
}

output "vnet_id" {
  value = azurerm_virtual_network.vnet.id
}

output "webapp_url" {
  value = azurerm_linux_web_app.webapp.default_hostname
}

output "vm_public_ip" {
  value = azurerm_public_ip.vm_pip.ip_address
}
