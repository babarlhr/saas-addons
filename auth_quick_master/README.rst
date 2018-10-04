.. image:: https://img.shields.io/badge/license-LGPL--3-blue.png
   :target: https://www.gnu.org/licenses/lgpl
   :alt: License: LGPL-3

===============================
 Quick Authentication (Master)
===============================

Authentication provider for ``auth_quick`` module.

Allows users from group ``Quick authentication for builds`` be authenticated as any user from the build. Access levels to builds can be extented in a custom module.

How it works
============

Base idea is similar to OAuth protocol.

* User is authenticated in master odoo database (where this module is installed)
* User opens url in the build (where ``auth_quick`` module is installed): build-123.example.com/quick-auth/login?login=admin (this module doesn't provider UI with such links)
* Build redirects User back to master odoo with build reference
* Master odoo creates record in model ``auth_quick_master.token`` with fields

  * ``user_id``
  * ``login``
  * ``token``
  * ``build``

* Master odoo redirects User back to the build with new url: build-123.example.com/quick-auth/check-token?token=abcdf456789
* Build validate the token by sending direct request to Master odoo and initialize session if token is avalid

Credits
=======

Contributors
------------
* `Ivan Yelizariev <https://it-projects.info/team/yelizariev>`__

Sponsors
--------
* `IT-Projects LLC <https://it-projects.info>`__

Maintainers
-----------
* `IT-Projects LLC <https://it-projects.info>`__

      To get a guaranteed support
      you are kindly requested to purchase the module
      at `odoo apps store <https://apps.odoo.com/apps/modules/12.0/auth_quick_master/>`__.

      Thank you for understanding!

      `IT-Projects Team <https://www.it-projects.info/team>`__

Further information
===================

Demo: http://runbot.it-projects.info/demo/saas-addons/12.0

HTML Description: https://apps.odoo.com/apps/modules/12.0/auth_quick_master/

Usage instructions: `<doc/index.rst>`_

Changelog: `<doc/changelog.rst>`_

Notifications on updates: `via Atom <https://github.com/it-projects-llc/saas-addons/commits/12.0/auth_quick_master.atom>`_, `by Email <https://blogtrottr.com/?subscribe=https://github.com/it-projects-llc/saas-addons/commits/12.0/auth_quick_master.atom>`_

Tested on Odoo 12.0 1868713dbd07e0b518f91dffe73e62d85e6ab9a6
