import { openModal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';

/** Sidebar "Change password" → dialog backed by Supabase Auth. */
export function initAccount() {
    const link = document.getElementById('nav-change-password');
    if (!link) return;
    link.addEventListener('click', (e) => {
        e.preventDefault();
        document.getElementById('sidebar-user-dropdown')?.classList.remove('visible');
        openModal('change-password-modal', {
            onOpen({ form }) { form.reset(); },
            async onSubmit(form) {
                const password = form.elements.password.value;
                if (password !== form.elements.confirm.value) throw new Error('Passwords do not match.');
                const { error } = await window._supabase.auth.updateUser({ password });
                if (error) throw new Error(error.message || 'Could not update password.');
                toast('Password updated');
            },
        });
    });
}
