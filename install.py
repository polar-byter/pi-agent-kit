"""Open setup or update the kit files of an existing project."""
import sys

if __name__ == '__main__':
    if '--update' in sys.argv[1:]:
        from kit.pi_project_update import main
        raise SystemExit(main(sys.argv[1:]))
    from kit.pi_installer_ui import main
    raise SystemExit(main())
